import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CguComponent } from './cgu.component';
import { fournisseursDeTest } from '../../../testing/test-providers';

describe('CguComponent', () => {
  let component: CguComponent;
  let fixture: ComponentFixture<CguComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [CguComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(CguComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
