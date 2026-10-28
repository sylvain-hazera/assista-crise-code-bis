import { ComponentFixture, TestBed } from '@angular/core/testing';

import { GuideComponent } from './guide.component';
import { fournisseursDeTest } from '../../testing/test-providers';

describe('GuideComponent', () => {
  let component: GuideComponent;
  let fixture: ComponentFixture<GuideComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [GuideComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(GuideComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
