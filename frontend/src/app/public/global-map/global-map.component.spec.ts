import { ComponentFixture, TestBed } from '@angular/core/testing';

import { GlobalMapComponent } from './global-map.component';
import { fournisseursDeTest } from '../../testing/test-providers';

describe('GlobalMapComponent', () => {
  let component: GlobalMapComponent;
  let fixture: ComponentFixture<GlobalMapComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [GlobalMapComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(GlobalMapComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
